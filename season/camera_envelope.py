"""Conservative swept target bounds, in the reference camera's world space."""
import itertools


def swept_target_corners(rows, subjects, box_size, follow_actor=None, reference=None):
    bounds={name:[[float('inf')]*3,[float('-inf')]*3] for name in subjects}
    for row in rows:
        delta=[0.,0.,0.] if follow_actor is None else [a-b for a,b in zip(row['actors'][follow_actor]['position'],reference)]
        for name in subjects:
            if name=='box':
                point=row['props']['box']['position']
                radius=[box_size[0]/2,box_size[2]/2,box_size[1]/2]
            else:
                p=row['actors'][name]['position'];point=[p[0],p[1],p[2]+1.5];radius=[.17,.17,.20]
            lo,hi=bounds[name]
            for i in range(3):
                lo[i]=min(lo[i],point[i]-delta[i]-radius[i])
                hi[i]=max(hi[i],point[i]-delta[i]+radius[i])
    return {('PROP_box' if name=='box' else name+'_head'):
            [list(point) for point in itertools.product(*zip(lo,hi))] for name,(lo,hi) in bounds.items()}
